import numpy
import time
import scipy.sparse
import argparse
from anewton import logistic, newton_update
from utils import *

def parse_args():
    parser = argparse.ArgumentParser(description = 'Collective Matrix Factorization')
    parser.add_argument('--train' , type = str, default = '', help = 'Training file')
    parser.add_argument('--test' , type = str, default = '', help = 'Testing file')
    parser.add_argument('--user' , type = str, default = '', help = 'User features')
    parser.add_argument('--item' , type = str, default = '', help = 'Item features')
    parser.add_argument('--out', type = str, default = '', help = 'File where fianl result will be saved')

    parser.add_argument('--alphas' , type = str, default = '0.4-0.3-0.3', help = 'Alpha in [0, 1] weights the relative importance of relations')
    parser.add_argument('--k', type = int, default = 10, help = 'Dimension of latent fectors')
    parser.add_argument('--reg', type = float, default = 0.1, help = 'Regularization for latent facotrs')
    parser.add_argument('--lr', type = float, default = 0.1, help = 'Initial learning rate for training')

    parser.add_argument('--max_iter', type = int, default = 100, help = 'Max training iteration')
    parser.add_argument('--tol', type = float, default = 0.5, help = 'Tolerant for change in training loss')
    parser.add_argument('--verbose', type = int, default = 1, help = 'Verbose or not')
    return parser.parse_args()

def learn(Xs, Xstst, rc_schema, modes, alphas, K, reg, learn_rate, max_iter, tol, verbose):
    assert(rc_schema.shape[0] == len(Xs) and rc_schema.shape[1] == 2) # schema match data
    assert(numpy.all(rc_schema[:, 0] != rc_schema[:, 1])) # should not have symmetric relations
    assert(rc_schema.shape[0] == len(alphas))
    assert(rc_schema.shape[0] == len(modes))
    check_modes(modes) 

    Xts = [None] * len(Xs)
    for i in range(len(Xs)):
        if Xs[i] is not None:
            Xts[i] = scipy.sparse.csc_matrix(Xs[i].T) # Transpose
            Xs[i] = scipy.sparse.csc_matrix(Xs[i]) # no Transpose
        if Xstst[i] is not None:
            Xstst[i] = scipy.sparse.csc_matrix(Xstst[i])

    [S, Ns] = get_config(Xs, rc_schema)

    # randomly initialize factor matrices with small values
    Us = [None] * S
    for i in range(S):
        Us[i] = numpy.random.rand(Ns[i], K) / numpy.sqrt(K)

    prev_loss = loss(Us, Xs, rc_schema, modes, alphas, reg)
    i = 0
    while i < max_iter:
        i += 1
        # training 
        tic = time.time()
        for t in range(S):
            newton_update(Us, Xs, Xts, rc_schema, alphas, modes, K, reg, learn_rate, Ns, t)
        
        # evaluation
        training_loss = loss(Us, Xs, rc_schema, modes, alphas, reg)
        change_rate = (prev_loss-training_loss)/prev_loss * 100
        prev_loss = training_loss

        if verbose == 1:
            # Ystst = predict(Us, Xstst, rc_schema, modes)
            # testing_loss = RMSE(Xstst[0], Ystst[0])
            toc = time.time()
            print("[CMF] Iteration {}/{}. Time: {:.1f}".format(i, max_iter, toc - tic))
            print("[CMF] Training Loss: {:.2f} (change {:.2f}%)".format(training_loss, change_rate))
            # print("[CMF] Testing RMSE: {:.2f}".format(testing_loss))
            
        # early stop
        if change_rate < tol and i != 1:
            break

    return Us

def loss(Us, Xs, rc_schema, modes, alphas, reg=0):
	'''
	Calculate objective loss
	See page 4: Generalizing to Arbitrary Schemas
	'''
	assert(rc_schema.shape[0] == len(Xs) and rc_schema.shape[1] == 2)

	Ys = predict(Us, Xs, rc_schema, modes)
	
	res = 0
	num_relation = len(Xs)
	# computing regularization for each latent factor
	for i in range(num_relation):
		for j in range(num_relation):
			if rc_schema[j, 0]==i or rc_schema[j, 1]==i:
				res += alphas[j] * reg * numpy.linalg.norm(Us[i].flat) # l2 norm

	# computing loss for each relation
	for j in range(num_relation):     
		alpha_j = alphas[j]
		if Xs[j] is None or Ys[j] is None or alpha_j == 0:
			continue

		X = scipy.sparse.csc_matrix(Xs[j])
		Y = scipy.sparse.csc_matrix(Ys[j])

		if modes[j] == 'sparse':
			assert( X.size == Y.size )
			res += alpha_j * numpy.sum(pow(X.data - Y.data, 2))

		elif modes[j] == 'dense' or modes[j] == 'log_dense':
			assert( numpy.all(Y.shape == X.shape) )
			res += alpha_j * numpy.sum(pow(X.toarray() - Y.toarray(), 2))   

	return res

def predict(Us, Xs, rc_schema, modes):
    '''
    see page 3: RELATIONAL SCHEMAS
    return a list of csc_matrix
    '''
    Ys = []
    for i in range(len(Xs)): # i = 1
        if Xs[i] is None:
        	# no need to predict Y
            Ys.append(None) 
            continue
        
        X = Xs[i]
        U = Us[rc_schema[i, 0]] 
        V = Us[rc_schema[i, 1]]

        if modes[i] == 'sparse':
            # predict only for non-zero elements in X
            X = scipy.sparse.csc_matrix(X)
            data = X.data.copy()
            indices = X.indices.copy()
            indptr = X.indptr.copy()
           
            for j in range(X.shape[1]): # for each column in X
                inds_j = indices[indptr[j]:indptr[j+1]]
                # indptr[j]:indptr[j+1] points to the data on j-th column of X
                if inds_j.size == 0:
                    continue
                data[indptr[j]:indptr[j+1]] = numpy.dot(U[inds_j, :], V[j, :])
            Y = scipy.sparse.csc_matrix((data, indices, indptr), X.shape)
            Ys.append(Y)

        elif modes[i] == 'dense':
            # predict for all elements in X
            Y = numpy.dot(U, V.T)
            Y = scipy.sparse.csc_matrix(Y)
            Ys.append(Y)

        elif modes[i] == 'log_dense':
            # predict for all elements in X
            Y = numpy.dot(U, V.T)
            Y = logistic(Y)
            Y = scipy.sparse.csc_matrix(Y)
            Ys.append(Y)

    return Ys

def run_cmf(Xs_trn, Xs_tst, rc_schema, modes, args):
    '''
    run cmf and return rmse
    '''
    alphas = string2list(args.alphas, len(modes))

    if args.verbose == 1:
        start_time = time.time()
        print('[Settings] k = {}. reg = {}. lr = {}. alpha = {}'.format(args.k, args.reg, args.lr, alphas))

    Us = learn(Xs_trn, Xs_tst, rc_schema, modes, alphas, args.k, args.reg, args.lr, args.max_iter, args.tol, args.verbose)
    Ys_tst = predict(Us, Xs_tst, rc_schema, modes)
    rmse = RMSE(Xs_tst[0], Ys_tst[0])

    if args.verbose == 1:
        end_time = time.time()
        print('[Results] k = {}. reg = {}. lr = {}. alpha = {}'.format(args.k, args.reg, args.lr, alphas))
        print('[Results] RMSE = {:.4f}'.format(rmse))
        print('[Results] Total Running Time: {:.0f} s'.format(end_time - start_time) )

    return rmse


if __name__ == "__main__":
    args = parse_args()
    [Xs_trn, Xs_tst, rc_schema, modes] = read_triple_data(args.train, args.test, args.user, args.item)

    if args.verbose == 1: 
        [S, Ns] = get_config(Xs_trn, rc_schema)
        print('------------------- CMF -------------------')
        print('[Data] Number of instnace for each entity = {}'.format(Ns))
        print('[Data] Training size = {}. Testing size = {}'.format(Xs_trn[0].size, Xs_tst[0].size))

    rmse = run_cmf(Xs_trn, Xs_tst, rc_schema, modes, args)
    save_result(args, rmse)
    
